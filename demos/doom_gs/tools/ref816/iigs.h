/*
 * A minimal Apple IIgs around the cpu816 core: what upstream's DOOM uses
 * once its loader has run, and nothing else.
 *
 *   memory   8 MB of RAM in banks $00-$7F, and banks $E0-$E1. Banks $00
 *            and $01 have the I/O space at $C000-$CFFF and the ROM at
 *            $D000-$FFFF unless bit 6 of the shadow register is set, when
 *            they are plain RAM (the game puts its interrupt vectors
 *            there). Banks $E0 and $E1 always have the I/O space. There
 *            is no ROM image: ROM reads give 0 and are counted, and so
 *            are accesses to banks with no memory; the reads also by
 *            the instruction that made them (iigs_counts).
 *   shadow   $C035: writes to banks $00/$01 copied to $E0/$E1 for the
 *            text pages, the hi-res pages and (bank $01 only) the super
 *            hi-res screen, each unless its inhibit bit is set.
 *   video    $C029, $C034 and the text switches are registers only; the
 *            vertical blank flag ($C019 bit 7) follows the NTSC frame
 *            (262 lines of 912 master clocks, the flag from line 192).
 *   time     master clocks of 14.31818 MHz. A CPU cycle takes 5 of them
 *            in fast mode (2.86 MHz) and 14 in slow mode ($C036 bit 7).
 *            iigs_set_cpu_hz gives fast mode another rate, as an
 *            accelerator would; every access still takes one cycle (an
 *            ideal 65816 with memory of uniform speed, no wait states).
 *   sound    the DOC and the sound GLU (doc.h).
 *   input    the ADB microcontroller (adb.h).
 *   disk     the ProDOS block driver and SmartPort entries of slot 7
 *            are trapped when the CPU reaches them (with the I/O space
 *            mapped in) and served from a disk image held in memory:
 *            block reads and writes, SmartPort STATUS and CONTROL. The
 *            slot's ROM has the one byte that locates the driver, $C7FF,
 *            so that upstream's loader can run too.
 *
 * Nothing here reads the host clock or anything random: a run depends
 * only on the image, the disk and the input.
 */
#ifndef IIGS_H
#define IIGS_H

#include <stddef.h>
#include <stdint.h>

#include "adb.h"
#include "cpu816.h"
#include "doc.h"

enum {
    IIGS_MASTER_HZ = 14318180,
    IIGS_FAST_CLOCKS = 5,               /* master clocks per CPU cycle */
    IIGS_SLOW_CLOCKS = 14,
    IIGS_LINE_CLOCKS = 912,             /* 65 cycles of the 1 MHz side */
    IIGS_FRAME_LINES = 262,
    IIGS_FRAME_CLOCKS = IIGS_LINE_CLOCKS * IIGS_FRAME_LINES,
    IIGS_VBL_LINE = 192,

    IIGS_RAM_BANKS = 0x80,
    IIGS_BANK = 0x10000,

    /* The slot of the boot drive and its firmware entries, as the
       loader finds them: the ProDOS block driver at $Cn00 + ($CnFF),
       SmartPort 3 bytes after it. tools/ref816/make_image.py writes
       the same addresses into BOOTINFO. */
    IIGS_DISK_SLOT = 7,
    IIGS_DRIVER_ENTRY = 0xc70a,
    IIGS_SMARTPORT_ENTRY = IIGS_DRIVER_ENTRY + 3,
    IIGS_DISK_UNIT = IIGS_DISK_SLOT << 4,   /* ProDOS unit: drive 1 */
    IIGS_FIRMWARE_CYCLES = 2000,        /* the time a firmware call takes */
    IIGS_READ_SITES = 16,               /* sites kept of each kind of read */

    /* Shadow register bits: set means inhibited. */
    IIGS_SHADOW_TEXT1 = 0x01, IIGS_SHADOW_HIRES1 = 0x02,
    IIGS_SHADOW_HIRES2 = 0x04, IIGS_SHADOW_SHR = 0x08,
    IIGS_SHADOW_AUX_HIRES = 0x10, IIGS_SHADOW_TEXT2 = 0x20,
    IIGS_SHADOW_IOLC = 0x40,

    /* Interrupt sources on the CPU's IRQ line. */
    IIGS_IRQ_DOC = 0x01, IIGS_IRQ_ADB = 0x02
};

/* Why iigs_run returned. */
typedef enum {
    IIGS_LIMIT,                 /* the cycle or frame limit */
    IIGS_BREAK,                 /* the next instruction is at a breakpoint */
    IIGS_SPIN,                  /* an instruction jumped to itself */
    IIGS_ODD_OPCODE,            /* WDM or STP was executed */
    IIGS_REQUEST                /* the step hook set stop_request */
} iigs_stop;

/* Reads of one instruction that the model answers with 0: the address of
   the instruction (the last opcode fetched), the lowest and highest
   address it read, and how many bytes. */
typedef struct {
    uint32_t pc, first, last;
    uint64_t count;
} iigs_read_site;

/* What the model met and does not implement, so that a run can say how
   far it relied on the model. */
typedef struct {
    uint32_t io_reads[256];     /* $C0xx registers not modelled */
    uint32_t io_writes[256];
    uint64_t rom_reads, rom_writes;     /* banks $00/$01 $D000-$FFFF */
    uint64_t slot_rom_reads;            /* $C100-$CFFF */
    uint64_t unmapped_reads, unmapped_writes;
    /* Where the ROM reads and the unmapped reads came from, by reading
       instruction, the first IIGS_READ_SITES of each; the reads of any
       further instruction are counted in read_sites_lost. */
    iigs_read_site rom_read_sites[IIGS_READ_SITES];
    iigs_read_site unmapped_read_sites[IIGS_READ_SITES];
    unsigned rom_read_site_count, unmapped_read_site_count;
    uint64_t read_sites_lost;
    uint64_t driver_calls, smartport_calls, firmware_errors;
    /* The cycles the firmware traps charged (IIGS_FIRMWARE_CYCLES a
       call), which no instruction of the game made. */
    uint64_t firmware_cycles;
    uint64_t interrupts;        /* IRQ vector fetches */
    /* BRK and COP, which go through the vectors the game sets, and
       WDM and STP, which the game never uses: they mean that the CPU
       runs data. */
    uint64_t brk, cop, wdm, stp;
    uint32_t first_brk_pc;      /* where the first BRK or COP was */
} iigs_counts;

typedef struct iigs {
    cpu816 cpu;
    uint8_t *ram;               /* banks $00-$7F */
    uint8_t *mega;              /* banks $E0-$E1 */

    uint8_t shadow, speed, newvideo, border;
    uint8_t text;               /* $C050/$C051: 1 = text mode */
    uint8_t inten, vgc_int;     /* $C041, $C023 as written */

    doc doc;
    adb adb;

    /* The master clock is clock_base + (cycles - cycle_base) *
       clock_num / clock_den, rounded down; the base moves when the
       speed changes. Fast mode takes fast_num / fast_den clocks a
       cycle. */
    uint64_t clock_base, cycle_base;
    uint64_t clock_num, clock_den;
    uint64_t fast_num, fast_den;
    uint64_t next_event;        /* master clock of the next DOC sample,
                                   ADB event or frame start */
    uint64_t frame;             /* video frames started since power-on */
    uint64_t instructions;      /* opcode fetches (MVN and MVP fetch
                                   theirs again for each byte) */

    uint8_t *breaks;            /* a bit for each 24-bit PC, or NULL */
    int break_passed;           /* iigs_run stopped at the current PC */
    int stop_on_fault;          /* iigs_run returns IIGS_SPIN and
                                   IIGS_ODD_OPCODE */
    uint8_t opcode;             /* the last opcode fetched */
    uint32_t opcode_pc;         /*   and its address */
    int odd_opcode;             /* WDM or STP since the start of the
                                   last iigs_run */

    uint8_t *disk;              /* the disk image, 512-byte blocks */
    uint32_t disk_blocks;
    int disk_written;

    /* Called by iigs_run after each instruction, interrupt entry,
       firmware call or idle cycle, with `step_context` (trace.c); NULL
       for none, so that an untraced run pays one test a step. */
    void (*after_step)(void *context);
    void *step_context;
    /* Set by the step hook to make iigs_run return IIGS_REQUEST after
       this step (footprint.c: the end of a --call); iigs_run clears it. */
    int stop_request;

    iigs_counts counts;
} iigs;

/* Allocate the memory and power on: RAM clear, fast mode, shadow
   register $08, CPU registers as cpu816_init leaves them, no
   breakpoints. Returns 0 when the memory cannot be allocated. */
int iigs_init(iigs *m);
void iigs_free(iigs *m);

/* Soft switches as a loader left them. */
void iigs_set_switches(iigs *m, uint8_t newvideo, uint8_t border,
                       uint8_t shadow, uint8_t speed);

/* Put bytes in RAM (banks $00-$7F, $E0, $E1), with no I/O or shadowing.
   Returns 0 when a byte would fall outside that memory. */
int iigs_load(iigs *m, uint32_t address, const uint8_t *data, size_t length);

/* A byte of RAM, without side effects: never I/O. 0 outside RAM. */
uint8_t iigs_peek(const iigs *m, uint32_t address);

/* The address in bank $E0 or $E1 that a CPU write to `address` in bank
   $00 or $01 also goes to under the shadow register as it is now, or
   IIGS_NO_SHADOW. (No shadowed range reaches the I/O space.) */
#define IIGS_NO_SHADOW UINT32_MAX
uint32_t iigs_shadow_target(const iigs *m, uint32_t address);

/* The disk the firmware traps serve; `data` stays the caller's and
   receives the writes. `length` must be a multiple of 512. */
void iigs_attach_disk(iigs *m, uint8_t *data, size_t length);

/* The CPU rate of fast mode in Hz; 0 for the IIgs's own (5 master
   clocks a cycle). Takes effect at once when the machine is fast. */
void iigs_set_cpu_hz(iigs *m, uint32_t hz);

/* The master clock now. */
uint64_t iigs_clock(const iigs *m);

/* Bit 7 of $C019: the vertical blank. */
int iigs_vbl(const iigs *m);

/* Stop iigs_run before the instruction at PBR:PC `address`. Returns 0
   when the bitmap cannot be allocated. */
int iigs_set_break(iigs *m, uint32_t address);

/* Run until the CPU has made `cycle_limit` cycles or frame
   `frame_limit` has started, whichever comes first (IIGS_LIMIT). Stops
   before an instruction at a breakpoint (IIGS_BREAK), except the first
   one after such a stop, so that a caller can go on. When
   stop_on_fault is set, also stops after an instruction that left PC
   where it was (IIGS_SPIN): a branch to itself, which only an
   interrupt could leave (MVN and MVP repeat that way on purpose and do
   not count); and after WDM or STP (IIGS_ODD_OPCODE), with its
   address in opcode_pc. Stops after a step whose hook set
   stop_request (IIGS_REQUEST). */
iigs_stop iigs_run(iigs *m, uint64_t cycle_limit, uint64_t frame_limit);

/* FNV-1a (64 bits) over banks $00-$7F then $E0-$E1. */
uint64_t iigs_ram_hash(const iigs *m);

#endif
