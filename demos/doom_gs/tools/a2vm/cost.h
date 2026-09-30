/*
 * The cost model of a2vm (docs/MILESTONES.md, milestone 3.1): the time a
 * program takes on the Appletini, in fabric clocks of its FPGA
 * (133.333 MHz), access by access.
 *
 * Every bus access the core makes is classed as the Appletini's vTW core
 * would route it in TURBO mode (hdl/apple/vtw_core_top.sv of
 * appletini-one, F1.2.1), and charged:
 *
 *   - fast memory (main and base aux, on-chip BRAM): through the TURBO
 *     caches, a 32-word read cache and a 32-entry write page table
 *     (vtw_turbo_cache.sv), 2 clocks on a hit, 4 or 5 on a miss;
 *   - extended memory (RamWorks banks 1-127, PSRAM): through the one-line
 *     8-byte write-allocate cache, 5 clocks on a hit, a PSRAM operation
 *     on a clean miss and two on a dirty one, each admitted at most once
 *     an Apple cycle (psram_simple.sv);
 *   - a $Cxxx access: a real bus cycle synchronised to the Apple clock,
 *     or one of the core's private shortcuts ($C011-$C01F status reads,
 *     the slot-7 SmartPort window, internal ROM);
 *   - a video write (main text and HGR pages, aux $0400-$0BFF and
 *     $2000-$9FFF): 6 clocks, and a byte for the mirror, which drains to
 *     the motherboard at one byte an Apple cycle; the next $Cxxx access
 *     waits while "active" bytes are pending, and an "exposure" access
 *     waits until every pending byte is out;
 *   - a change of the memory mapping: both TURBO caches are cleared;
 *   - a memory API request: the CPU hold, the mirror and line flushes,
 *     and the ARM's per-descriptor and per-byte work (memory_api_hw.c);
 *   - with the virtual Phasor enabled (slowdown_slot4, off in f121 and
 *     fastpath), the slot-4 slowdown: after an access to $C400-$C4FF or
 *     $C0C0-$C0CF, slowdown_cycles CPU cycles at 1 MHz, each paced to an
 *     Apple data strobe (README.md, "The slot-4 slowdown").
 *
 * Its parameters come from a file of "name value" lines, which
 * tools/a2vm/costs.py writes from a profile of tools/a2vm/costs/appletini.json,
 * where each parameter cites its source.
 *
 * The model only observes: it never changes what the machine does. In
 * "timed" mode its clock is the machine's clock (the VBL, $C019, the
 * mouse interrupt and the idle skips follow it); otherwise it runs beside
 * the machine's own clock, and a compatibility run still matches
 * a2sim.py.
 */
#ifndef A2VM_COST_H
#define A2VM_COST_H

#include <stdint.h>
#include <stdio.h>

struct a2vm;

enum { COST_PHASES = 16, COST_RW_LINES_MAX = 64 };

/* The parameters, in fabric clocks unless the name says otherwise. */
typedef struct {
    /* clocks */
    double fabric_mhz, line_us;
    unsigned lines, vbl_line;
    /* the TURBO path of an access to fast memory */
    unsigned turbo_hit, turbo_read_miss, turbo_write_miss, posted_write;
    double turbo_extra;             /* the calibratable parameter: extra
                                       clocks an access to fast memory */
    int caches_survive;             /* fastpath: no invalidation on a
                                       mapping change */
    /* extended memory */
    unsigned rw_hit, rw_request, psram_read, psram_write;
    unsigned rw_lines;              /* lines of the RamWorks cache */
    unsigned admit_offset, admit_window;
    int relaxed_admission;          /* fastpath: no admission window */
    unsigned drain_rmw;             /* clocks a captured aux write keeps
                                       the PSRAM busy (relaxed) */
    /* $Cxxx */
    unsigned io_capture, io_route, video_wait, bus_drive_tap,
        bus_data_tap, bus_done, status_read, sp_private, rom_read,
        quiet_switch;
    int quiet_switches;             /* fastpath */
    int read_bank;                  /* fastpath: $C069 */
    /* the video mirror */
    unsigned flush_steer_cycles;
    int lazy_shr;                   /* fastpath */
    /* the memory API */
    double axi_us, axi_write_us, ps_dispatch_us;
    unsigned amem_chunk, amem_request_axi, amem_begin_axi,
        amem_poll_axi, amem_end_axi, amem_dma_axi, amem_dma_poll_axi,
        amem_read_word_axi, amem_read_setup_axi, amem_write_word_axi,
        amem_write_setup_axi, amem_write_byte_axi;
    int keep_lazy;                  /* fastpath: holds keep lazy bytes */
    /* the slot-4 slowdown (README.md, "The slot-4 slowdown") */
    unsigned slowdown_cycles;       /* the window, in CPU cycles */
    int slowdown_slot4;             /* the virtual Phasor is enabled: slot
                                       4 is in the slowdown mask */
    int slowdown_via_exempt;        /* FW-S1: VIA port writes do not open
                                       the window */
    unsigned slow_done;             /* clocks from data_en to the end of a
                                       paced memory cycle */
} a2vm_cost_params;

typedef struct {
    uint64_t accesses;              /* core cycles charged ("steps") */
    uint64_t dropped;               /* dummy reads TURBO omits */
    uint64_t read_hits;             /* TURBO word-cache read hits */
    uint64_t misses;                /* TURBO lookups without a hit */
    uint64_t invalidations;
    uint64_t video_wait;            /* clocks, as perf_count[7] */
    uint64_t bus_cycles;            /* real sync cycles */
    uint64_t posted;                /* bytes written to the motherboard */
    uint64_t io_accesses, io_private, quiet;
    uint64_t rw_accesses, rw_hits, rw_misses, rw_dirty, rw_wait;
    uint64_t barrier_wait, flush_wait, flushes, lazy_flushes, lazy_wait;
    uint64_t reconcile_cycles;
    uint64_t amem_requests, amem_bytes, amem_clocks;
    uint64_t fast_clocks, rw_clocks, io_clocks, video_clocks;
    /* the slot-4 slowdown, reported only when it is on */
    uint64_t slow_hits;             /* accesses that (re)open the window */
    uint64_t slow_cycles;           /* cycles run at 1 MHz by the window */
    uint64_t slow_clocks;           /* the clocks of those cycles */
} a2vm_cost_counters;

typedef struct a2vm_cost {
    a2vm_cost_params p;
    double period;                  /* fabric clocks an Apple cycle */
    uint64_t t;                     /* the model's clock */
    a2vm_cost_counters c;

    /* the TURBO caches */
    uint8_t word_valid[32];
    uint16_t word_tag[32];
    uint32_t word_phys[32];
    uint8_t map_valid[32], map_fast[32];
    uint8_t map_tag[32];
    uint32_t map_phys[32];
    uint32_t mapping;               /* the translation state, packed */

    /* the RamWorks line cache: lines, LRU order by `used` */
    struct { uint32_t line; uint8_t valid, dirty; uint64_t used; }
        rw[COST_RW_LINES_MAX];
    uint64_t rw_use;
    int64_t admit_cycle;            /* the Apple cycle of the last
                                       admission */
    uint64_t psram_free;            /* relaxed: when the PSRAM is idle */
    int64_t bus_next;               /* the first Apple cycle the bus engine
                                       has free (one sync or posted cycle a
                                       cycle, vtw_bus_engine.sv:840-880) */
    double extra_fraction;

    /* the video mirror: bytes by 17-bit address (bit 16: aux) */
    uint64_t *drain_at;             /* active bytes: when each drains */
    uint64_t active_end, aux_drain_end;
    uint8_t *deferred;              /* 1 deferred, 2 lazy */
    uint32_t *deferred_list;
    uint32_t deferred_count, lazy_count, deferred_aux, lazy_aux;
    uint32_t list_used;

    /* the switches the motherboard has seen (quiet switches) */
    uint8_t phys_bank, phys_ramrd, phys_altzp, phys_lc_read,
        phys_lc_write, phys_lc_bank2;
    int shr_selected;

    /* phases */
    int phase_addr;                 /* -1: none */
    unsigned phase;
    uint64_t phase_start, phase_clocks[COST_PHASES];

    /* the report: one JSON line a frame boundary */
    FILE *report;
    uint64_t last_t, last_phase[COST_PHASES];
    a2vm_cost_counters last_c;
    int timed;

    /* the slot-4 slowdown: CPU cycles left at 1 MHz (slow_cnt_q), and
       whether the instruction running started in TURBO
       (instruction_turbo_q of w65c02_core.sv) */
    unsigned slow_left;
    int instr_turbo;
} a2vm_cost;

/* Read a parameter file ("name value" lines, # comments). Returns 0 and
   a message in `error` if a parameter is missing, unknown or malformed. */
int a2vm_cost_load(a2vm_cost_params *p, const char *path, char *error,
                   size_t error_size);

a2vm_cost *a2vm_cost_new(const a2vm_cost_params *p);
void a2vm_cost_free(a2vm_cost *c);

/* The clocks a video frame and the vertical blanking start take, for a
   machine run on the model's clock. */
uint64_t a2vm_cost_frame_clocks(const a2vm_cost *c);

/* Take the machine's present state as the model's (switches the
   motherboard has seen, SHR selected). */
void a2vm_cost_attach(struct a2vm *m);

/* The bus hooks (a2vm.c): before each access, with the page a2vm maps
   for it (NULL: its slow path) and the cycle kind of cpu65c02.h; after
   each slow-path access, to see a mapping change. */
void a2vm_cost_read(struct a2vm *m, uint16_t address, const uint8_t *page,
                    int kind);
void a2vm_cost_write(struct a2vm *m, uint16_t address, uint8_t value,
                     const uint8_t *page, int kind);
void a2vm_cost_after_io(struct a2vm *m, uint16_t address, int write,
                        uint8_t value);
/* The machine skipped `clocks` of an idle loop (a2vm.c skip_idle): the
   slowdown window runs out as it would have. */
void a2vm_cost_skip(struct a2vm *m, uint64_t clocks);
/* A memory API CONTROL request that the model executed. */
void a2vm_cost_amem(struct a2vm *m, const uint8_t *request, size_t length);
/* A frame boundary: one line of the report. */
void a2vm_cost_boundary(struct a2vm *m, uint64_t boundary);
void a2vm_cost_final(struct a2vm *m, FILE *out);

#endif
