/*
 * a2vm: the model of the DOOM GS port's target, an enhanced Apple //e
 * with an Appletini card (docs/MILESTONES.md, milestone 3.1).
 *
 * This file is the machine around the W65C02S core of cpu65c02.h:
 *
 *   - the enhanced //e memory map with 128 RamWorks banks of 64 KB
 *     selected by $C071/$C073, RAMRD, RAMWRT, ALTZP, 80STORE, PAGE2,
 *     HIRES and the language card of main and of each aux bank;
 *   - the devices the existing Doom port touches: keyboard, $C019, Open
 *     and Solid Apple, paddles, speaker, NEWVIDEO, the Appletini mouse
 *     card in slot 2 with its VBL interrupt, the Phasor in slot 4 (its
 *     registers), and the memory API FIFO at $CFF0-$CFF2 in slot 7;
 *   - a trap of the ProDOS MLI entry (prodos.h);
 *   - optionally, the zero-page bank pair of the firmware design
 *     (docs/firmware/zpbank-spec.md, as zpbank-review.md corrects it),
 *     which is not in F1.2.1: off unless armed.
 *
 * Every rule follows demos/doom/tools/a2sim.py, the Python model the
 * existing port was developed on, so that the two can be compared cycle
 * for cycle; README.md lists where a2sim.py itself departs from the
 * hardware.
 *
 * Two cores run on this bus:
 *
 *   A2VM_CORE_PY65     the compatibility core (py65core.h): the
 *                      instruction semantics, memory accesses and cycle
 *                      counts of py65's 65C02, the core a2sim.py uses,
 *                      with a2sim.py's I/O surcharge, interrupt delivery
 *                      and idle skipping. Runs of it match a2sim.py
 *                      exactly (tools/a2vm/compare_a2sim.py).
 *   A2VM_CORE_W65C02S  the exact W65C02S of cpu65c02_core.h: every bus
 *                      cycle of the chip, dummy reads included, one cycle
 *                      a bus access.
 *
 * The machine is deterministic: it reads no host time and no randomness.
 */
#ifndef A2VM_H
#define A2VM_H

#include "cost.h"
#include "cpu65c02.h"
#include "prodos.h"

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

enum {
    A2VM_BANK_SIZE = 0x10000,
    A2VM_MAX_BANKS = 128,
    A2VM_FRAME_1MHZ = 17030,        /* 262 lines of 65 cycles */
    A2VM_LINES = 262,
    A2VM_VBL_LINE = 192,
    A2VM_TURBO_FRAME = 1250000,     /* a2sim.py's historical "turbo" frame */
    A2VM_MAX_IDLE = 16,
    A2VM_MAX_IRQ_BOUNDS = 8,
    A2VM_MAX_KEYS = 256,
    A2VM_AMEM_BUFFER = 0x10100
};

typedef enum { A2VM_CORE_PY65, A2VM_CORE_W65C02S } a2vm_core;

/* The switches of a2sim.Machine.sw, in the order of its SWITCH_PAIRS
   ($C000-$C00F writes set the pair low >> 1) then the video switches. */
typedef enum {
    SW_STORE80, SW_RAMRD, SW_RAMWRT, SW_INTCXROM, SW_ALTZP, SW_SLOTC3ROM,
    SW_COL80, SW_ALTCHAR, SW_TEXT, SW_MIXED, SW_PAGE2, SW_HIRES, SW_COUNT
} a2vm_switch;

extern const char *const a2vm_switch_names[SW_COUNT];

/* The Appletini's AppleMouse-compatible card (a2sim.MouseCard,
   hdl/apple/mouse_card.sv). */
typedef struct {
    int32_t x, y;
    uint8_t buttons, prev_buttons;
    uint8_t moved, move_irq, button_pending, vbl_pending, irq;
    uint8_t mode, clamp_axis, seq, connected;
    int32_t clamp[2][2];            /* per axis: min, max */
    int32_t ps_x, ps_y;
    uint8_t ps_buttons;
    uint64_t log_reads, log_writes; /* a2sim's log, counted */
} a2vm_mouse;

/* The Phasor in slot 4, as far as a2sim.Phasor models it. */
typedef struct {
    int64_t t1_start[2];
    uint8_t mode;
    struct { uint8_t orb, ora, ddrb, ddra; } via[2];
    uint8_t ay[4][16];
    uint8_t latched[4];
    uint8_t selected[2][2];
    uint8_t ssi_dur, ssi_rate, ssi_running;
    int64_t ssi_started;
    uint64_t ssi_phonemes;
    uint64_t ay_writes;             /* a2sim's log, counted */
} a2vm_phasor;

/* The memory API of README_MEMORY_API.md (version 1) behind the FIFO at
   $CFF0-$CFF2, as a2sim.FakeSmartPortMemory models it. */
typedef struct {
    uint8_t supported, available, private_port, never_ready;
    uint8_t selected, ready;
    uint8_t rom[256];
    uint8_t caps[32];
    uint8_t *input;                 /* A2VM_AMEM_BUFFER bytes */
    size_t input_length;
    uint8_t output[64];
    size_t output_length;
    uint64_t requests, completed;
    uint8_t last_family, last_result;
} a2vm_amem;

/* An idle loop the model skips (a2sim.Machine.idle_pcs): at `pc`, when
   every condition holds, time moves to the next VBL or the next line 0
   instead of the loop running. */
typedef enum { A2VM_IDLE_VBL, A2VM_IDLE_LINE0 } a2vm_idle_kind;

typedef struct {
    uint16_t pc;
    uint8_t kind;                   /* a2vm_idle_kind */
    uint8_t need_main_zp;           /* ALTZP must be off */
    uint8_t need_vbl;               /* in vertical blanking */
    uint8_t compare;                /* the two main words below are equal */
    uint16_t word_a, word_b;
} a2vm_idle;

/* A range of storage, for the write log and range snapshots: the
   storage kinds of a2vm_storage (main, aux bank, main LC $C000-$FFFF,
   main LC bank 1 $D000-$DFFF), or A2VM_RANGE_CPU, the CPU's address
   whatever it reaches (I/O and write-protected pages included). An aux
   bank's language card is in its $C000-$FFFF: bank 2 at $D000-$FFFF,
   bank 1 at $C000-$CFFF. `low` and `high` are inclusive. */
enum {
    A2VM_RANGE_MAIN, A2VM_RANGE_AUX, A2VM_RANGE_LC, A2VM_RANGE_LC1,
    A2VM_RANGE_CPU, A2VM_MAX_RANGES = 256
};

typedef struct {
    uint8_t kind, bank_low, bank_high;  /* banks: aux only */
    uint16_t low, high;
} a2vm_range;

/* The zero-page bank pair. `address` is the pair's first byte (zp_rd),
   0 when the pair is off; zp_wr is address + 1. `rd` and `wr` are the
   registers: 0 follows the switches, 1-126 is the $C073 bank that data
   reads (writes) of $0200-$BFFF reach. */
typedef struct {
    uint8_t armed, address, rd, wr;
    uint64_t enables;               /* $C069 writes while armed */
    uint64_t loads;                 /* main zero-page writes that set rd
                                       or wr */
    uint64_t reads, writes;         /* redirected accesses */
    uint64_t firmware;              /* redirected accesses made with the
                                       PC in $C100-$CFFF or in the ROM */
    uint64_t amem;                  /* memory API requests made with rd or
                                       wr nonzero */
} a2vm_zpbank;

/* The registers of the compatibility core (py65's MPU). P keeps bit 4 as
   py65 does: set by reset, PLP and RTI, cleared by an interrupt. */
typedef struct {
    uint16_t pc;
    uint8_t a, x, y, sp, p;
    uint8_t waiting;
} a2vm_py65_regs;

typedef struct a2vm {
    a2vm_core core;
    a2vm_py65_regs r;               /* A2VM_CORE_PY65 */
    cpu65c02 cpu;                   /* A2VM_CORE_W65C02S */
    uint64_t py65_cycles;           /* the clock of the compatibility core */
    uint64_t *clock;                /* the clock of the core in use */

    /* time */
    uint64_t frame_cycles, vbl_start, io_cycles, next_vbl;
    uint64_t frame_1mhz;            /* Apple cycles a video frame */
    uint64_t idle_cycles, irqs, io_accesses;
    uint64_t video_writes, shr_writes, speaker_toggles;
    uint64_t instructions;

    /* memory */
    uint8_t main[A2VM_BANK_SIZE];
    uint8_t lc[0x4000];             /* main LC: index = address - $C000 */
    uint8_t lc1[0x1000];            /* main LC bank 1 $D000-$DFFF */
    uint8_t rom[0x4000];            /* $C000-$FFFF */
    uint8_t *aux_banks;             /* ramworks_banks * 64 KB */
    uint8_t *aux;                   /* the selected bank */
    unsigned ramworks_banks, bank;
    uint8_t sw[SW_COUNT];
    uint8_t lc_read, lc_write, lc_prewrite, lc_bank2;
    uint8_t newvideo;

    /* the pages of $0000-$FFFF for reads and writes; NULL is the slow
       path. wflag: 1 counts a video write, 3 a video and an SHR write */
    const uint8_t *rpage[256];
    uint8_t *wpage[256];
    uint8_t wflag[256];

    /* keyboard, game port, speaker */
    struct { uint64_t when; uint8_t key; } keys[A2VM_MAX_KEYS];
    unsigned key_count;
    uint8_t key_latch, key_held;
    uint8_t buttons[3];
    int64_t paddles[4], paddle_trigger;

    /* slots */
    int mouse_on, phasor_slot, mouse_slot;
    a2vm_mouse mouse;
    a2vm_phasor phasor;
    int amem_on;
    a2vm_amem amem;

    /* the MLI trap */
    a2vm_prodos *prodos;
    uint8_t mli_hi_pending, mli_hi_value;
    uint16_t mli_hi_address;

    a2vm_idle idle[A2VM_MAX_IDLE];
    unsigned idle_count;
    uint8_t idle_map[8192];         /* one bit a PC with an idle entry */

    /* the cost model (cost.h), or NULL */
    a2vm_cost *cost;

    /* An observer of every CPU write, for test harnesses (NULL in a
       normal run): the address, the storage byte the write reaches (NULL
       for I/O and write-protected pages) and the value. It is called
       before the write and changes nothing. */
    void (*write_hook)(struct a2vm *m, uint16_t address, uint8_t *storage,
                       uint8_t value);
    void *hook_context;

    /* set by a device when the run must end: a request a2sim.py's
       models reject with an assertion, or a ProDOS volume they cannot
       build */
    char halt[256];

    /* --ay-log (README.md, "The AY log"): a line for each AY register
       write that reaches a chip, each chip reset, each interrupt taken
       and each RTI. NULL in every other run; it only observes. */
    FILE *ay_log;

    /* --via-ora-nh: a write to a VIA's register 15 (ORA without
       handshake) sets ORA, as the card's 6522 does (via6522.v:149).
       a2sim.py ignores the register, so it is off by default. */
    int via_ora_nh;

    /* --phasor-mb-only: the card locked to Mockingboard mode, as the
       card's audio_control bit 26 does (mockingboard.sv:38-41): the
       $C0C0-$C0CF mode switch is ignored, so the card keeps one AY behind
       each VIA. Off by default. */
    int phasor_mb_only;

    /* --irq-bounds (README.md, "Interrupt bounds"): the address ranges an
       interrupt handler may access, from its first instruction to its
       RTI; any other access halts the run. irq_guard is set while such a
       handler runs. irq_bound_count is 0 in every other run. */
    uint16_t irq_bounds[A2VM_MAX_IRQ_BOUNDS][2];
    unsigned irq_bound_count;
    int irq_guard;

    /* The PC of the instruction running (set by a2vm_step), for the
       write log. */
    uint16_t instruction_pc;

    /* --write-log (README.md, "The write log"): a line for each CPU
       write that reaches one of the ranges, made by the write_hook that
       a2vm_start_write_log sets. NULL in every other run; it only
       observes. */
    FILE *write_log;
    a2vm_range write_ranges[A2VM_MAX_RANGES];
    unsigned write_range_count;
    uint64_t write_logged;
    uint64_t write_log_limit;   /* lines; 0 for none. The write that would
                                   pass it halts the run */

    /* The zero-page bank pair (README.md, "The zero-page bank pair";
       docs/firmware/zpbank-spec.md as corrected by zpbank-review.md).
       zpb.armed is 0 in every run without --zpbank or a pair profile
       (f121zp, fastzp): the machine is then F1.2.1's exactly. */
    a2vm_zpbank zpb;
} a2vm;

typedef struct {
    const char *rom_path;           /* NULL: no ROM (zeros) */
    const uint8_t *rom;             /* or the 16 KB directly */
    a2vm_core core;
    int turbo;                      /* a2sim's speed "turbo" */
    unsigned speed;                 /* else its numeric speed (MHz) */
    int64_t io_cycles;              /* -1: a2sim's default for the speed */
    unsigned ramworks_banks;        /* 1-128 */
    int mouse, phasor_slot, mouse_slot;
    int amem;                       /* attach the memory API */
} a2vm_config;

void a2vm_default_config(a2vm_config *config);

/* Allocate and power on: a2sim.Machine.__init__ (registers of py65's
   reset, the booted zero page). Returns NULL out of memory, with the
   reason in `error`. */
a2vm *a2vm_new(const a2vm_config *config, char *error, size_t error_size);
void a2vm_free(a2vm *m);

/* Attach the MLI trap (FakeProDOS.attach): writes JMP $BF00 at $BF00 and
   the launched program's path at $0280. The machine takes ownership. */
void a2vm_attach_prodos(a2vm *m, a2vm_prodos *prodos);

/* The memory API options of FakeSmartPortMemory. */
void a2vm_amem_options(a2vm *m, int supported, int available,
                       int private_port);

/* One step of a2sim.Machine.step: the VBL event, interrupt delivery and
   the idle skip, then one instruction. */
void a2vm_step(a2vm *m);

/* The clock, in the cycles of the core in use. */
static inline uint64_t a2vm_now(const a2vm *m) { return *m->clock; }

uint16_t a2vm_pc(const a2vm *m);
void a2vm_set_register(a2vm *m, char name, unsigned value);  /* p a x y s */
uint8_t a2vm_register(const a2vm *m, char name);

/* The CPU bus, with every side effect. */
uint8_t a2vm_read(a2vm *m, uint16_t address);
void a2vm_write(a2vm *m, uint16_t address, uint8_t value);

/* Storage by kind, without side effects: 0 main, 1 aux `bank`, 2 the main
   LC (address $C000-$FFFF), 3 the main LC bank 1 ($D000-$DFFF). NULL
   when outside. */
uint8_t *a2vm_storage(a2vm *m, int kind, unsigned bank, uint16_t address);

/* After a change of the switches from outside the CPU. */
void a2vm_remap(a2vm *m);
void a2vm_select_bank(a2vm *m, unsigned value);

int a2vm_add_idle(a2vm *m, const a2vm_idle *idle);

/* Attach the cost model (the machine owns it from then on). With `timed`
   the model's clock becomes the machine's: a video frame of `lines`
   lines lasts the model's frame, and $C000-$CFFF accesses take no extra
   cycles. Call before the run starts. */
void a2vm_attach_cost(a2vm *m, a2vm_cost *cost, int timed);

/* Input, as a2sim.Machine's methods of the same names. */
void a2vm_press(a2vm *m, uint8_t key, uint64_t at_cycle);
void a2vm_hold(a2vm *m, uint8_t key);
void a2vm_release(a2vm *m);
void a2vm_mouse_move(a2vm *m, int64_t x, int64_t y);
void a2vm_mouse_delta(a2vm *m, int64_t dx, int64_t dy);
void a2vm_mouse_buttons(a2vm *m, int left, int right);

int a2vm_in_vbl(const a2vm *m);
uint64_t a2vm_bus_clock(const a2vm *m);

/* The memory API request execution (exposed for the tests of main.c's
   bus scripts). */
size_t a2vm_amem_execute(a2vm *m, uint8_t family, const uint8_t *request,
                         size_t length, uint8_t *reply);

/* The zero-page bank pair: arm it (the firmware's kill switch on), or
   disarm it, which turns it off. Arming needs the exact core and 128
   RamWorks banks; returns 0 with the reason in `error` otherwise. */
int a2vm_zpbank_arm(a2vm *m, int on, char *error, size_t error_size);
/* Start the write log: `log` gets a line for each CPU write into
   m->write_ranges. It is the machine's write_hook, so a harness cannot
   use both. */
void a2vm_start_write_log(a2vm *m, FILE *log);
/* RES#: the pair turns off (zpbank-spec.md section 4). */
void a2vm_zpbank_reset(a2vm *m);
/* A data access of the CPU at an effective address (kind DATA_EA of
   cpu65c02.h): what the core's ST_MEM_READ and ST_MEM_WRITE do, the
   pair's redirection included. For bus scripts. */
uint8_t a2vm_read_ea(a2vm *m, uint16_t address);
void a2vm_write_ea(a2vm *m, uint16_t address, uint8_t value);
/* The CPU RESET sequence of the exact core, with RES#'s effect on the
   pair. The //e's own reset of the switches is not modelled (a2sim.py
   has none). */
void a2vm_cpu_reset(a2vm *m);

/* Where a storage byte is: its kind (A2VM_RANGE_MAIN ... LC1), bank
   and offset in that storage. 0 when `p` is not storage (the ROM). */
int a2vm_locate(const a2vm *m, const uint8_t *p, unsigned *kind,
                unsigned *bank, unsigned *offset);
/* Does the range list hold a write of the CPU's `address` reaching
   storage `p` (NULL: none)? */
int a2vm_in_ranges(const a2vm *m, const a2vm_range *ranges, unsigned count,
                   uint16_t address, const uint8_t *p);
/* Parse RANGES (README.md, "Ranges"); 0 with the reason in `error`. */
int a2vm_parse_ranges(const char *text, a2vm_range *ranges,
                      unsigned *count, int allow_cpu, char *error,
                      size_t error_size);

#endif
